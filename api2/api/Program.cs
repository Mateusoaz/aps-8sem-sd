using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Serialization;
using Microsoft.Data.Sqlite;

var app = WebApplication.CreateBuilder(args).Build();
var cs = new SqliteConnectionStringBuilder { DataSource = Environment.GetEnvironmentVariable("DB_PATH") ?? Path.GetFullPath("../data/alagamentos.db") }.ToString();
await Db.Init(cs, "leituras_alagamento", "sensor TEXT NOT NULL,nivel_corrego REAL NOT NULL,chuva_acumulada REAL NOT NULL");
app.MapPost("/api/v1/sensores/{sourceId}/ocorrencias", async (string sourceId, Ocorrencia payload, HttpRequest request) => {
  if (string.IsNullOrWhiteSpace(payload.Fonte?.Id) || string.IsNullOrWhiteSpace(payload.Fonte.Tipo) || string.IsNullOrWhiteSpace(payload.Sensor) || string.IsNullOrWhiteSpace(payload.DataColetada) || payload.Dados is null) return Results.BadRequest(new { erro="Campos obrigatórios ausentes" });
  if (request.Headers.TryGetValue("X-Source-Id",out var header) && header != payload.Fonte.Id) return Results.BadRequest(new { erro="X-Source-Id diverge de fonte.id" });
  if (sourceId != payload.Fonte.Id) return Results.NotFound(new { erro="A rota deve usar o mesmo sensor de fonte.id" });
  return await Db.Save(cs,payload.Fonte,payload.DataColetada,payload,"leituras_alagamento","sensor,nivel_corrego,chuva_acumulada","$sensor,$nivel,$chuva",c=>{c.Parameters.AddWithValue("$sensor",payload.Sensor);c.Parameters.AddWithValue("$nivel",payload.Dados.NivelCorrego);c.Parameters.AddWithValue("$chuva",payload.Dados.ChuvaAcumulada);});
});
app.MapGet("/health/live", () => Results.Ok(new { status = "live", instancia = Environment.MachineName }));
app.MapGet("/health/ready", async () =>
{
  try
  {
    await using var connection = new SqliteConnection(cs);
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
app.Run("http://0.0.0.0:"+(Environment.GetEnvironmentVariable("PORT")??"3002"));
record Fonte(string Id,string Tipo,[property: JsonPropertyName("organização")] string? Organizacao); record Dados(double NivelCorrego,double ChuvaAcumulada); record Ocorrencia(Fonte Fonte,string Sensor,string DataColetada,Dados Dados);
static class Db { public static async Task Init(string cs,string table,string columns){await using var c=new SqliteConnection(cs);await c.OpenAsync();var q=c.CreateCommand();q.CommandText=$"PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS ingestoes(id INTEGER PRIMARY KEY AUTOINCREMENT,source_id TEXT NOT NULL,source_type TEXT NOT NULL,source_organization TEXT,collected_at TEXT NOT NULL,received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,payload_hash TEXT NOT NULL UNIQUE,payload_json TEXT NOT NULL); CREATE TABLE IF NOT EXISTS {table}(ingestion_id INTEGER PRIMARY KEY REFERENCES ingestoes(id),{columns});";await q.ExecuteNonQueryAsync();} public static async Task<IResult> Save<T>(string cs,Fonte f,string date,T p,string t,string n,string v,Action<SqliteCommand> add){var json=System.Text.Json.JsonSerializer.Serialize(p);var hash=Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(json))).ToLowerInvariant();await using var c=new SqliteConnection(cs);await c.OpenAsync();var e=c.CreateCommand();e.CommandText="SELECT id FROM ingestoes WHERE payload_hash=$hash";e.Parameters.AddWithValue("$hash",hash);if(await e.ExecuteScalarAsync() is long old)return Results.Ok(new{status="já recebido",ingestionId=old});await using var tx=(SqliteTransaction)await c.BeginTransactionAsync();try{var i=c.CreateCommand();i.Transaction=tx;i.CommandText="INSERT INTO ingestoes(source_id,source_type,source_organization,collected_at,payload_hash,payload_json) VALUES($id,$type,$org,$date,$hash,$json) RETURNING id";i.Parameters.AddWithValue("$id",f.Id);i.Parameters.AddWithValue("$type",f.Tipo);i.Parameters.AddWithValue("$org",(object?)f.Organizacao??DBNull.Value);i.Parameters.AddWithValue("$date",date);i.Parameters.AddWithValue("$hash",hash);i.Parameters.AddWithValue("$json",json);var id=(long)(await i.ExecuteScalarAsync())!;var r=c.CreateCommand();r.Transaction=tx;r.CommandText=$"INSERT INTO {t}(ingestion_id,{n}) VALUES($id,{v})";r.Parameters.AddWithValue("$id",id);add(r);await r.ExecuteNonQueryAsync();await tx.CommitAsync();return Results.Created($"/ingestoes/{id}",new{status="recebido",ingestionId=id});}catch(Exception x){await tx.RollbackAsync();return Results.Problem(x.Message,statusCode:500);}}}
