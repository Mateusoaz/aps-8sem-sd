using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using ThermalInversion.Api.Data;
using ThermalInversion.Api.Models;
using ThermalInversion.Api.Options;

namespace ThermalInversion.Api.Services;

/// <summary>
/// Regra: temperatura superior maior que a da superfície = inversão térmica detectada.
/// O alerta é gerado quando a inversão COMEÇA (leitura anterior da estação sem inversão ou inexistente).
/// Por enquanto roda de forma síncrona dentro do POST; numa etapa futura vira um consumidor de fila.
/// </summary>
public class AlertService(ThermalInversionDbContext db, IOptions<AlertOptions> options, ILogger<AlertService> logger)
{
    public async Task EvaluateTemperatureProfileAsync(TemperatureProfileReading reading, CancellationToken ct)
    {
        // Gradiente positivo suficiente significa que a camada superior está mais quente.
        var minGradient = options.Value.MinInversionGradientC;
        var gradient = reading.UpperTemperatureC - reading.SurfaceTemperatureC;

        if (gradient <= minGradient)
            return;

        // Busca o último perfil anterior da estação para distinguir início de continuação.
        var previousGradient = await db.TemperatureProfiles
            .AsNoTracking()
            .Where(r => r.StationId == reading.StationId && r.Id != reading.Id && r.Timestamp <= reading.Timestamp)
            .OrderByDescending(r => r.Timestamp).ThenByDescending(r => r.Id)
            .Select(r => (double?)(r.UpperTemperatureC - r.SurfaceTemperatureC))
            .FirstOrDefaultAsync(ct);

        // A inversão já estava em curso: o alerta deste episódio já foi emitido
        // Se o perfil anterior já era uma inversão, não duplica o alerta do mesmo episódio.
        if (previousGradient > minGradient)
            return;

        // Guarda o gradiente medido e o limite usado, para a resposta ser auditável depois.
        db.Alerts.Add(new Alert
        {
            Type = Alert.InversionDetected,
            StationId = reading.StationId,
            AreaId = reading.AreaId,
            Value = gradient,
            Threshold = minGradient,
            Message = $"Inversão térmica na estação {reading.StationId}: camada superior {gradient:0.0} °C mais quente que a superfície.",
            Timestamp = reading.Timestamp,
            CreatedAt = DateTimeOffset.UtcNow,
        });
        await db.SaveChangesAsync(ct);

        logger.LogWarning("Alerta {Type} na estação {StationId}: gradiente = {Gradient} °C",
            Alert.InversionDetected, reading.StationId, gradient);
    }
}
