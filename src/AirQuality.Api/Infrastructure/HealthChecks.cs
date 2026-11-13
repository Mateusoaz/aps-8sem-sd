using AirQuality.Api.Data;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Npgsql;

namespace AirQuality.Api.Infrastructure;

/// <summary>
/// Readiness: abre uma conexão e roda SELECT 1, a cada chamada da probe.
///   banco fora -> Unhealthy -> HTTP 503 -> o pod sai do Service (sem reiniciar)
///
/// Usa um pool de conexões SEPARADO, de uma conexão só (no Npgsql, connection string diferente = pool
/// diferente). Se a probe usasse o pool das requisições, sob carga ela esperaria uma conexão livre até
/// estourar o tempo, e o kubelet tiraria do Service um pod que está atendendo normalmente. A pergunta da
/// readiness é "consigo falar com o banco?", e não "o meu pool está livre?".
/// </summary>
public class DatabaseHealthCheck(IConfiguration configuration, DatabaseStatus status) : IHealthCheck
{
    private readonly string _conexao = new NpgsqlConnectionStringBuilder(configuration.GetConnectionString("Default"))
    {
        ApplicationName = "readiness",
        MaxPoolSize = 1,
        Timeout = 2,          // segundos para abrir a conexão
        CommandTimeout = 2,
    }.ConnectionString;

    public async Task<HealthCheckResult> CheckHealthAsync(HealthCheckContext context, CancellationToken ct = default)
    {
        if (!status.IsReady)
            return HealthCheckResult.Unhealthy("criando o banco e as tabelas");
        try
        {
            await using var conexao = new NpgsqlConnection(_conexao);
            await conexao.OpenAsync(ct);
            await using var comando = new NpgsqlCommand("SELECT 1", conexao);
            await comando.ExecuteScalarAsync(ct);
            return HealthCheckResult.Healthy();
        }
        catch (Exception ex)
        {
            return HealthCheckResult.Unhealthy(ex.Message);
        }
    }
}
