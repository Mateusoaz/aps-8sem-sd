using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using ThermalInversion.Api.Data;
using ThermalInversion.Api.Models;
using ThermalInversion.Api.Options;

namespace ThermalInversion.Api.Services;

/// <summary>
/// Regra: temperatura superior maior que a da superfície = inversão térmica detectada.
/// O alerta é gerado quando a inversão COMEÇA (leitura anterior da estação sem inversão ou inexistente).
/// Roda no consumidor da fila (AlertConsumer); se a fila estiver desligada ou fora do ar, dentro do próprio POST.
/// </summary>
public class AlertService(ThermalInversionDbContext db, IOptions<AlertOptions> options, ILogger<AlertService> logger)
{
    /// <summary>Chamado pelo consumidor da fila: a mensagem traz só o id da leitura.</summary>
    public async Task EvaluateByIdAsync(long readingId, CancellationToken ct)
    {
        var reading = await db.TemperatureProfiles.AsNoTracking().FirstOrDefaultAsync(r => r.Id == readingId, ct);
        if (reading is null)
        {
            logger.LogWarning("Leitura {ReadingId} não encontrada: mensagem descartada.", readingId);
            return;
        }
        await EvaluateTemperatureProfileAsync(reading, ct);
    }

    public async Task EvaluateTemperatureProfileAsync(TemperatureProfileReading reading, CancellationToken ct)
    {
        var minGradient = options.Value.MinInversionGradientC;
        var gradient = reading.UpperTemperatureC - reading.SurfaceTemperatureC;

        if (gradient <= minGradient)
            return;

        var previousGradient = await db.TemperatureProfiles
            .AsNoTracking()
            .Where(r => r.StationId == reading.StationId && r.Id != reading.Id && r.Timestamp <= reading.Timestamp)
            .OrderByDescending(r => r.Timestamp).ThenByDescending(r => r.Id)
            .Select(r => (double?)(r.UpperTemperatureC - r.SurfaceTemperatureC))
            .FirstOrDefaultAsync(ct);

        // A inversão já estava em curso: o alerta deste episódio já foi emitido
        if (previousGradient > minGradient)
            return;

        // Idempotência: a fila entrega "pelo menos uma vez", então a mesma leitura pode ser avaliada duas vezes
        if (await db.Alerts.AnyAsync(a => a.Type == Alert.InversionDetected && a.StationId == reading.StationId
                                          && a.Timestamp == reading.Timestamp, ct))
            return;

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
