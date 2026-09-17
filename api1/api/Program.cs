using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Serialization;
using Microsoft.Data.Sqlite;

var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();
var dbPath = Environment.GetEnvironmentVariable("DB_PATH") ?? Path.GetFullPath("../data/qualidade_ar.db");
var connectionString = new SqliteConnectionStringBuilder { DataSource = dbPath }.ToString();
await Database.Initialize(connectionString, "leituras_qualidade_ar", "estacao TEXT NOT NULL, mp25 REAL NOT NULL, co REAL NOT NULL, no3 REAL NOT NULL, temperatura_c REAL NOT NULL");
app.MapGet("/health/live", () => Results.Ok(new { status = "live" }));
app.MapGet("/health/ready", () => Results.Ok(new { status = "ready" }));

app.MapPost("/api/v1/sensores/{sourceId}/leituras", async (string sourceId, Leitura payload, HttpRequest request) =>
{
    if (string.IsNullOrWhiteSpace(payload.Fonte?.Id) || string.IsNullOrWhiteSpace(payload.Fonte.Tipo) || string.IsNullOrWhiteSpace(payload.Estacao) || string.IsNullOrWhiteSpace(payload.DataColetada) || payload.Dados is null)
        return Results.BadRequest(new { erro = "Campos obrigatórios ausentes" });
    if (request.Headers.TryGetValue("X-Source-Id", out var header) && header != payload.Fonte.Id) return Results.BadRequest(new { erro = "X-Source-Id diverge de fonte.id" });
    if (sourceId != payload.Fonte.Id) return Results.NotFound(new { erro = "A rota deve usar o mesmo sensor de fonte.id" });
    return await Database.Save(connectionString, payload.Fonte, payload.DataColetada, payload, "leituras_qualidade_ar", "estacao,mp25,co,no3,temperatura_c", "$estacao,$mp25,$co,$no3,$temp", cmd => { cmd.Parameters.AddWithValue("$estacao", payload.Estacao); cmd.Parameters.AddWithValue("$mp25", payload.Dados.Mp25); cmd.Parameters.AddWithValue("$co", payload.Dados.Co); cmd.Parameters.AddWithValue("$no3", payload.Dados.No3); cmd.Parameters.AddWithValue("$temp", payload.Dados.Temp); });
});
app.Run("http://0.0.0.0:" + (Environment.GetEnvironmentVariable("PORT") ?? "3001"));

record Fonte(string Id, string Tipo, [property: JsonPropertyName("organização")] string? Organizacao);
record Dados(double Mp25, double Co, double No3, double Temp);
record Leitura(Fonte Fonte, string Estacao, string DataColetada, Dados Dados);

static class Database {
  public static async Task Initialize(string cs, string table, string columns) { await using var c=new SqliteConnection(cs); await c.OpenAsync(); var cmd=c.CreateCommand(); cmd.CommandText=$"PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS ingestoes (id INTEGER PRIMARY KEY AUTOINCREMENT,source_id TEXT NOT NULL,source_type TEXT NOT NULL,source_organization TEXT,collected_at TEXT NOT NULL,received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,payload_hash TEXT NOT NULL UNIQUE,payload_json TEXT NOT NULL); CREATE TABLE IF NOT EXISTS {table} (ingestion_id INTEGER PRIMARY KEY REFERENCES ingestoes(id),{columns});"; await cmd.ExecuteNonQueryAsync(); }
  public static async Task<IResult> Save<T>(string cs,Fonte fonte,string date,T payload,string table,string names,string values,Action<SqliteCommand> add) { var json=System.Text.Json.JsonSerializer.Serialize(payload); var hash=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(json))).ToLowerInvariant(); await using var c=new SqliteConnection(cs); await c.OpenAsync(); var exists=c.CreateCommand(); exists.CommandText="SELECT id FROM ingestoes WHERE payload_hash=$hash"; exists.Parameters.AddWithValue("$hash",hash); if(await exists.ExecuteScalarAsync() is long old) return Results.Ok(new { status="já recebido",ingestionId=old }); await using var tx=(SqliteTransaction)await c.BeginTransactionAsync(); try { var ingest=c.CreateCommand(); ingest.Transaction=tx; ingest.CommandText="INSERT INTO ingestoes(source_id,source_type,source_organization,collected_at,payload_hash,payload_json) VALUES($id,$type,$org,$date,$hash,$json) RETURNING id"; ingest.Parameters.AddWithValue("$id",fonte.Id); ingest.Parameters.AddWithValue("$type",fonte.Tipo); ingest.Parameters.AddWithValue("$org",(object?)fonte.Organizacao??DBNull.Value); ingest.Parameters.AddWithValue("$date",date); ingest.Parameters.AddWithValue("$hash",hash); ingest.Parameters.AddWithValue("$json",json); var id=(long)(await ingest.ExecuteScalarAsync())!; var reading=c.CreateCommand(); reading.Transaction=tx; reading.CommandText=$"INSERT INTO {table}(ingestion_id,{names}) VALUES($id,{values})"; reading.Parameters.AddWithValue("$id",id); add(reading); await reading.ExecuteNonQueryAsync(); await tx.CommitAsync(); return Results.Created($"/ingestoes/{id}",new {status="recebido",ingestionId=id}); } catch(Exception e) { await tx.RollbackAsync(); return Results.Problem(e.Message,statusCode:500); } }
}
