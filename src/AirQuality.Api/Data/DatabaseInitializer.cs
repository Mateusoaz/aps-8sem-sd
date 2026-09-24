using Microsoft.EntityFrameworkCore;

namespace AirQuality.Api.Data;

public static class DatabaseInitializer
{
    /// <summary>
    /// Cria o banco e as tabelas se ainda não existirem.
    /// Tenta várias vezes com espera: se o Postgres demorar a subir, a API espera em vez de morrer.
    /// </summary>
    public static async Task InitializeAsync(IServiceProvider services, ILogger logger, int maxAttempts = 10)
    {
        for (var attempt = 1; ; attempt++)
        {
            try
            {
                using var scope = services.CreateScope();
                var db = scope.ServiceProvider.GetRequiredService<AirQualityDbContext>();
                await db.Database.EnsureCreatedAsync();
                logger.LogInformation("Banco de dados pronto.");
                return;
            }
            catch (Exception ex) when (attempt < maxAttempts)
            {
                var delay = TimeSpan.FromSeconds(Math.Min(2 * attempt, 10));
                logger.LogWarning(ex, "Banco indisponível (tentativa {Attempt}/{MaxAttempts}). Nova tentativa em {Delay}s.",
                    attempt, maxAttempts, delay.TotalSeconds);
                await Task.Delay(delay);
            }
        }
    }
}
