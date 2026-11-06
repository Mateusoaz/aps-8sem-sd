using AirQuality.Api.Data;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Options;

namespace AirQuality.Api.Infrastructure;

// Readiness: as três dependências são verificadas A CADA chamada da probe.
//   banco fora  -> Unhealthy -> HTTP 503 -> o pod sai do Service (sem reiniciar)
//   Redis fora  -> Degraded  -> HTTP 200 -> continua atendendo, consultando direto no banco
//   fila fora   -> Degraded  -> HTTP 200 -> continua atendendo, avaliando o alerta dentro do POST
// Sem o banco a API não serve para nada; sem cache ou fila ela só fica mais lenta.

public class DatabaseHealthCheck(AirQualityDbContext db, DatabaseStatus status) : IHealthCheck
{
    public async Task<HealthCheckResult> CheckHealthAsync(HealthCheckContext context, CancellationToken ct = default)
    {
        if (!status.IsReady)
            return HealthCheckResult.Unhealthy("criando o banco e as tabelas");
        try
        {
            return await db.Database.CanConnectAsync(ct)
                ? HealthCheckResult.Healthy("conectado")
                : HealthCheckResult.Unhealthy("sem conexão");
        }
        catch (Exception ex)
        {
            return HealthCheckResult.Unhealthy(ex.Message);
        }
    }
}

public class CacheHealthCheck(RedisConnection redis, IOptions<CacheOptions> options) : IHealthCheck
{
    public async Task<HealthCheckResult> CheckHealthAsync(HealthCheckContext context, CancellationToken ct = default)
    {
        if (!options.Value.Enabled || !redis.Configured)
            return HealthCheckResult.Healthy("desligado");
        try
        {
            var latency = await redis.Database!.PingAsync();
            return HealthCheckResult.Healthy($"ping {latency.TotalMilliseconds:0.0} ms");
        }
        catch (Exception ex)
        {
            return HealthCheckResult.Degraded($"fora do ar, consultas vão direto ao banco ({ex.GetType().Name})");
        }
    }
}

public class QueueHealthCheck(ReadingQueue queue) : IHealthCheck
{
    public Task<HealthCheckResult> CheckHealthAsync(HealthCheckContext context, CancellationToken ct = default)
    {
        var result = !queue.Enabled ? HealthCheckResult.Healthy("desligada, alertas avaliados no POST")
            : queue.IsConnected ? HealthCheckResult.Healthy("conectada")
            : HealthCheckResult.Degraded("desconectada, alertas avaliados no POST");
        return Task.FromResult(result);
    }
}

public static class HealthResponse
{
    /// <summary>Corpo JSON da readiness: o estado de cada dependência e qual pod respondeu.</summary>
    public static Task WriteAsync(HttpContext context, HealthReport report)
    {
        context.Response.ContentType = "application/json";
        return context.Response.WriteAsJsonAsync(new
        {
            status = report.Status.ToString(),
            instancia = AppInfo.Instance,
            versao = AppInfo.Version,
            dependencias = report.Entries.ToDictionary(
                e => e.Key,
                e => new { status = e.Value.Status.ToString(), detalhe = e.Value.Description }),
        });
    }
}
