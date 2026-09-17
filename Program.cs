using Npgsql;

var builder = WebApplication.CreateBuilder(args);

// CONFIGURACAO EXTERNALIZADA: a string de conexao vem do ambiente.
// Nenhuma credencial fica escrita no codigo-fonte.
var conexao = Environment.GetEnvironmentVariable("CONNECTION_STRING")
              ?? throw new InvalidOperationException("Variavel CONNECTION_STRING nao definida.");

builder.Services.AddSingleton(new NpgsqlDataSourceBuilder(conexao).Build());

var app = builder.Build();
var fonte = app.Services.GetRequiredService<NpgsqlDataSource>();

// Identifica qual instancia respondeu -- util quando houver varias replicas.
var instancia = Environment.MachineName;
var pronto = false;

// O banco pode demorar a aceitar conexoes. A API nao pode morrer por isso:
// ela tenta em segundo plano e so fica "ready" quando conseguir.
_ = Task.Run(async () =>
{
    while (!pronto)
    {
        try
        {
            await using var cmd = fonte.CreateCommand(
                """
                CREATE TABLE IF NOT EXISTS leituras (
                    id            SERIAL PRIMARY KEY,
                    estacao       TEXT NOT NULL,
                    mp25          DOUBLE PRECISION NOT NULL,
                    registrado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """);
            await cmd.ExecuteNonQueryAsync();
            pronto = true;
            app.Logger.LogInformation("Banco pronto.");
        }
        catch (Exception ex)
        {
            app.Logger.LogWarning("Banco indisponivel ({Msg}). Nova tentativa em 2s.", ex.Message);
            await Task.Delay(2000);
        }
    }
});

// ---------- Saude ----------
// LIVENESS: o processo esta vivo? Se falhar, o orquestrador REINICIA o container.
app.MapGet("/health/live", () => Results.Ok(new { status = "live", instancia }));

// READINESS: esta apto a receber trafego? Se falhar, o orquestrador apenas
// TIRA o container do balanceamento -- sem matar o processo.
app.MapGet("/health/ready", () => pronto
    ? Results.Ok(new { status = "ready", instancia })
    : Results.StatusCode(503));

// READ - lista todas as leituras
app.MapGet("/leituras", async () =>
{
    var lista = new List<Leitura>();
    await using var cmd = fonte.CreateCommand(
        "SELECT id, estacao, mp25, registrado_em FROM leituras ORDER BY id");
    await using var r = await cmd.ExecuteReaderAsync();
    while (await r.ReadAsync())
        lista.Add(new Leitura(r.GetInt32(0), r.GetString(1), r.GetDouble(2), r.GetDateTime(3)));
    return Results.Ok(lista);
});

// CREATE - registra uma nova leitura
app.MapPost("/leituras", async (NovaLeitura dto) =>
{
    if (string.IsNullOrWhiteSpace(dto.Estacao))
        return Results.BadRequest(new { erro = "estacao e obrigatoria" });

    await using var cmd = fonte.CreateCommand(
        "INSERT INTO leituras (estacao, mp25) VALUES ($1, $2) RETURNING id, registrado_em");
    cmd.Parameters.AddWithValue(dto.Estacao);
    cmd.Parameters.AddWithValue(dto.Mp25);
    await using var r = await cmd.ExecuteReaderAsync();
    await r.ReadAsync();
    var criada = new Leitura(r.GetInt32(0), dto.Estacao, dto.Mp25, r.GetDateTime(1));
    return Results.Created($"/leituras/{criada.Id}", criada);
});

// UPDATE - corrige o valor de uma leitura existente
app.MapPut("/leituras/{id:int}", async (int id, NovaLeitura dto) =>
{
    await using var cmd = fonte.CreateCommand(
        "UPDATE leituras SET estacao = $1, mp25 = $2 WHERE id = $3 RETURNING registrado_em");
    cmd.Parameters.AddWithValue(dto.Estacao);
    cmd.Parameters.AddWithValue(dto.Mp25);
    cmd.Parameters.AddWithValue(id);
    await using var r = await cmd.ExecuteReaderAsync();
    if (!await r.ReadAsync())
        return Results.NotFound(new { erro = $"leitura {id} nao encontrada" });
    return Results.Ok(new Leitura(id, dto.Estacao, dto.Mp25, r.GetDateTime(0)));
});

// DELETE - remove uma leitura
app.MapDelete("/leituras/{id:int}", async (int id) =>
{
    await using var cmd = fonte.CreateCommand("DELETE FROM leituras WHERE id = $1");
    cmd.Parameters.AddWithValue(id);
    var afetadas = await cmd.ExecuteNonQueryAsync();
    return afetadas == 0
        ? Results.NotFound(new { erro = $"leitura {id} nao encontrada" })
        : Results.NoContent();
});

app.Run();

record NovaLeitura(string Estacao, double Mp25);
record Leitura(int Id, string Estacao, double Mp25, DateTime RegistradoEm);