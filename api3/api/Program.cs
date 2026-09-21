using System.Text.Json.Serialization;
using Npgsql;

var app = WebApplication.CreateBuilder(args).Build();
var cs = Environment.GetEnvironmentVariable("DATABASE_URL") ?? throw new InvalidOperationException("DATABASE_URL não configurada");
await PostgresStore.Initialize(cs, "eventos_transito", "veiculo TEXT NOT NULL,rodovia TEXT NOT NULL,velocidade_kmh DOUBLE PRECISION NOT NULL,placa TEXT");
await DomainStore.Initialize(cs,
  [new("br101-km200", "BR-101 km 200", "Posto de monitoramento rodoviário", null, null)],
  [
    new("radar-01", "velocidade", "Prefeitura", "br101-km200", "km/h", 80),
    new("fluxo-01", "fluxo-veicular", "Prefeitura", "br101-km200", "veículos/h", 1000),
    new("balanca-01", "pesagem", "Prefeitura", "br101-km200", "kg", 45000),
    new("camera-01", "reconhecimento-camera", "Prefeitura", "br101-km200", "confiança", null, ">=", "derivado")
  ]);
DomainStore.MapCommonRoutes(app, cs,
  new HashSet<string> { "velocidade", "fluxo-veicular", "pesagem", "reconhecimento-camera" });

app.MapPost("/api/v2/sensores/{sensorId}/velocidades", async (string sensorId, VelocidadeMedida payload, HttpRequest request) => {
  if (DomainStore.ValidateSource(request, sensorId) is { } error) return error;
  if (payload.VelocidadeKmh < 0) return Results.BadRequest(new { erro = "velocidadeKmh não pode ser negativa" });
  return (await DomainStore.SaveMeasurement(cs, sensorId, "velocidade", payload.DataColetada, payload.LocalId,
    new { payload.VelocidadeKmh, unidade = "km/h" }, payload.VelocidadeKmh)).Result;
});
app.MapPost("/api/v2/sensores/{sensorId}/fluxo-veicular", async (string sensorId, FluxoVeicular payload, HttpRequest request) => {
  if (DomainStore.ValidateSource(request, sensorId) is { } error) return error;
  if (payload.QuantidadeVeiculos < 0 || payload.OcupacaoPercentual is < 0 or > 100)
    return Results.BadRequest(new { erro = "Quantidade ou ocupação inválida" });
  return (await DomainStore.SaveMeasurement(cs, sensorId, "fluxo-veicular", payload.DataColetada, payload.LocalId,
    new { payload.QuantidadeVeiculos, payload.OcupacaoPercentual, periodoMinutos = payload.PeriodoMinutos }, payload.QuantidadeVeiculos)).Result;
});
app.MapPost("/api/v2/sensores/{sensorId}/pesagens", async (string sensorId, Pesagem payload, HttpRequest request) => {
  if (DomainStore.ValidateSource(request, sensorId) is { } error) return error;
  if (payload.PesoKg < 0) return Results.BadRequest(new { erro = "pesoKg não pode ser negativo" });
  return (await DomainStore.SaveMeasurement(cs, sensorId, "pesagem", payload.DataColetada, payload.LocalId,
    new { payload.PesoKg, payload.NumeroEixos, unidade = "kg" }, payload.PesoKg)).Result;
});
app.MapPost("/api/v2/cameras/{cameraId}/reconhecimentos", async (string cameraId, ReconhecimentoCamera payload, HttpRequest request) => {
  if (DomainStore.ValidateSource(request, cameraId) is { } error) return error;
  if (string.IsNullOrWhiteSpace(payload.Placa) || string.IsNullOrWhiteSpace(payload.TipoVeiculo) || payload.Confianca is < 0 or > 1)
    return Results.BadRequest(new { erro = "Reconhecimento inválido" });
  return (await DomainStore.SaveMeasurement(cs, cameraId, "reconhecimento-camera", payload.DataColetada, payload.LocalId,
    new { payload.Placa, payload.TipoVeiculo, payload.Confianca, origemDado = "derivado" })).Result;
});
app.MapPost("/api/v1/sensores/{sourceId}/eventos", async (string sourceId, Evento payload, HttpRequest request) => {
  if(string.IsNullOrWhiteSpace(payload.Fonte?.Id)||string.IsNullOrWhiteSpace(payload.Fonte.Tipo)||string.IsNullOrWhiteSpace(payload.Veiculo)||string.IsNullOrWhiteSpace(payload.DataColetada)||payload.Dados is null||string.IsNullOrWhiteSpace(payload.Dados.Rodovia))return Results.BadRequest(new{erro="Campos obrigatórios ausentes"});
  if(request.Headers.TryGetValue("X-Source-Id",out var header)&&header!=payload.Fonte.Id)return Results.BadRequest(new{erro="X-Source-Id diverge de fonte.id"}); if(sourceId!=payload.Fonte.Id)return Results.NotFound(new{erro="A rota deve usar o mesmo sensor de fonte.id"}); return await PostgresStore.Save(cs,payload.Fonte.Id,payload.Fonte.Tipo,payload.Fonte.Organizacao,payload.DataColetada,payload,"eventos_transito","veiculo,rodovia,velocidade_kmh,placa","@vehicle,@road,@speed,@plate",c=>{c.Parameters.AddWithValue("vehicle",payload.Veiculo);c.Parameters.AddWithValue("road",payload.Dados.Rodovia);c.Parameters.AddWithValue("speed",payload.Dados.Velocidade);c.Parameters.AddWithValue("plate",(object?)payload.Dados.Placa??DBNull.Value);});
});
app.MapGet("/api/v1/eventos", async (int? limite) =>
{
  if (limite is < 1 or > 1000)
    return Results.BadRequest(new { erro = "limite deve estar entre 1 e 1000" });

  var eventos = new List<object>();
  await using var connection = new NpgsqlConnection(cs);
  await connection.OpenAsync();
  await using var command = connection.CreateCommand();
  command.CommandText = """
      SELECT i.id, i.source_id, i.collected_at, i.received_at,
             e.veiculo, e.rodovia, e.velocidade_kmh, e.placa
      FROM ingestoes AS i
      JOIN eventos_transito AS e ON e.ingestion_id = i.id
      ORDER BY i.id DESC
      LIMIT @limite
      """;
  command.Parameters.AddWithValue("limite", limite ?? 100);
  await using var reader = await command.ExecuteReaderAsync();
  while (await reader.ReadAsync())
    eventos.Add(new
    {
      ingestionId = reader.GetInt64(0),
      fonteId = reader.GetString(1),
      dataColetada = reader.GetString(2),
      recebidoEm = reader.GetString(3),
      veiculo = reader.GetString(4),
      dados = new { rodovia = reader.GetString(5), velocidadeKmh = reader.GetDouble(6), placa = reader.IsDBNull(7) ? null : reader.GetString(7) }
    });
  return Results.Ok(eventos);
});
app.MapGet("/", () => Results.Redirect("/api/v1/eventos"));
app.MapGet("/health/live", () => Results.Ok(new { status = "live", instancia = Environment.MachineName }));
app.MapGet("/health/ready", async () =>
{
  try
  {
    await using var connection = new NpgsqlConnection(cs);
    await connection.OpenAsync();
    await using var command = connection.CreateCommand();
    command.CommandText = "SELECT 1";
    await command.ExecuteScalarAsync();
    return Results.Ok(new { status = "ready", instancia = Environment.MachineName });
  }
  catch (Exception)
  {
    return Results.StatusCode(503);
  }
});
app.Run("http://0.0.0.0:"+(Environment.GetEnvironmentVariable("PORT")??"3003"));
record Fonte(string Id,string Tipo,[property: JsonPropertyName("organização")] string? Organizacao); record Dados(string Rodovia,double Velocidade,string? Placa); record Evento(Fonte Fonte,string Veiculo,string DataColetada,Dados Dados);
record VelocidadeMedida(string DataColetada, string? LocalId, double VelocidadeKmh);
record FluxoVeicular(string DataColetada, string? LocalId, int QuantidadeVeiculos, double OcupacaoPercentual, int PeriodoMinutos);
record Pesagem(string DataColetada, string? LocalId, double PesoKg, int NumeroEixos);
record ReconhecimentoCamera(string DataColetada, string? LocalId, string Placa, string TipoVeiculo, double Confianca);
