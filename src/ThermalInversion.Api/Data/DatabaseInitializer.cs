using Microsoft.EntityFrameworkCore;

namespace ThermalInversion.Api.Data;

/// <summary>Diz se o banco e as tabelas já existem. A readiness só passa depois disso.</summary>
public class DatabaseStatus
{
    private volatile bool _ready;

    public bool IsReady => _ready;

    public void MarkReady() => _ready = true;
}

/// <summary>
/// Cria o banco e as tabelas em segundo plano, sem prender a partida da API.
///
/// No Kubernetes não existe depends_on: o pod da API pode subir antes do Postgres. Se a criação do banco
/// travasse a partida, a porta 8080 não abriria, a liveness falharia e o kubelet reiniciaria o pod em laço
/// (CrashLoopBackOff). Assim, a porta abre na hora (liveness OK) e o pod fica fora do balanceamento
/// (readiness falhando) até o banco ficar pronto. Tenta para sempre, com espera crescente até 10 s.
/// </summary>
public class DatabaseInitializer(IServiceProvider services, DatabaseStatus status, ILogger<DatabaseInitializer> logger)
    : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        for (var attempt = 1; !stoppingToken.IsCancellationRequested; attempt++)
        {
            try
            {
                using var scope = services.CreateScope();
                var db = scope.ServiceProvider.GetRequiredService<ThermalInversionDbContext>();
                await db.Database.EnsureCreatedAsync(stoppingToken);
                status.MarkReady();
                logger.LogInformation("Banco de dados pronto (tentativa {Attempt}).", attempt);
                return;
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                return;
            }
            catch (Exception ex)
            {
                // Várias réplicas sobem juntas e tentam criar o mesmo banco: quem perde a corrida
                // recebe "already exists" e, na tentativa seguinte, encontra tudo pronto.
                var delay = TimeSpan.FromSeconds(Math.Min(2 * attempt, 10));
                logger.LogWarning("Banco indisponível (tentativa {Attempt}): {Error}. Nova tentativa em {Delay} s.",
                    attempt, ex.Message, delay.TotalSeconds);
                try { await Task.Delay(delay, stoppingToken); }
                catch (OperationCanceledException) { return; }
            }
        }
    }
}
