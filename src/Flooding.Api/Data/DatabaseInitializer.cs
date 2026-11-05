using Microsoft.EntityFrameworkCore;

namespace Flooding.Api.Data;

public static class DatabaseInitializer
{
    /// <summary>
    /// Cria o banco e as tabelas se ainda não existirem.
    /// Tenta várias vezes com espera: se o Postgres demorar a subir, a API espera em vez de morrer.
    /// </summary>
    public static async Task InitializeAsync(IServiceProvider services, ILogger logger, int maxAttempts = 10)
    {
        // Compose/Kubernetes podem iniciar a API antes do PostgreSQL aceitar conexões.
        for (var attempt = 1; ; attempt++)
        {
            try
            {
                // DbContext é scoped; cria-se um escopo temporário para a inicialização.
                using var scope = services.CreateScope();
                var db = scope.ServiceProvider.GetRequiredService<FloodingDbContext>();
                await db.Database.EnsureCreatedAsync();
                logger.LogInformation("Banco de dados pronto.");
                return;
            }
            catch (Exception ex) when (attempt < maxAttempts)
            {
                // Espera progressivamente, com teto de 10 s; a última exceção encerra a partida.
                var delay = TimeSpan.FromSeconds(Math.Min(2 * attempt, 10));
                logger.LogWarning(ex, "Banco indisponível (tentativa {Attempt}/{MaxAttempts}). Nova tentativa em {Delay}s.",
                    attempt, maxAttempts, delay.TotalSeconds);
                await Task.Delay(delay);
            }
        }
    }
}
