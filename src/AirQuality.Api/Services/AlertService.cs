using AirQuality.Api.Data;
using AirQuality.Api.Models;
using AirQuality.Api.Options;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;

namespace AirQuality.Api.Services;

/// <summary>
/// Regra: PM2.5 acima do limite por N leituras seguidas da mesma estação.
/// O alerta é gerado uma vez por episódio (quando a sequência completa N), não a cada leitura.
/// Por enquanto roda de forma síncrona dentro do POST; numa etapa futura vira um consumidor de fila.
/// </summary>
public class AlertService(AirQualityDbContext db, IOptions<AlertOptions> options, ILogger<AlertService> logger)
{
    public async Task EvaluateParticulateAsync(ParticulateReading reading, CancellationToken ct)
    {
        var limit = options.Value.Pm25Limit;
        var required = options.Value.Pm25ConsecutiveReadings;

        if (reading.Pm25 <= limit)
            return;

        // As N+1 leituras mais recentes da estação (a atual inclusa)
        var recent = await db.ParticulateReadings
            .AsNoTracking()
            .Where(r => r.StationId == reading.StationId && r.Timestamp <= reading.Timestamp)
            .OrderByDescending(r => r.Timestamp).ThenByDescending(r => r.Id)
            .Select(r => r.Pm25)
            .Take(required + 1)
            .ToListAsync(ct);

        var lastN = recent.Take(required).ToList();
        var sequenceComplete = lastN.Count == required && lastN.All(v => v > limit);
        // Se a leitura anterior à sequência também estava acima, o alerta deste episódio já foi emitido
        var alreadyAlerted = recent.Count > required && recent[required] > limit;

        if (!sequenceComplete || alreadyAlerted)
            return;

        db.Alerts.Add(new Alert
        {
            Type = Alert.Pm25AboveLimit,
            StationId = reading.StationId,
            AreaId = reading.AreaId,
            Value = reading.Pm25,
            Threshold = limit,
            Message = $"PM2.5 acima de {limit} µg/m³ por {required} leituras seguidas na estação {reading.StationId}.",
            Timestamp = reading.Timestamp,
            CreatedAt = DateTimeOffset.UtcNow,
        });
        await db.SaveChangesAsync(ct);

        logger.LogWarning("Alerta {Type} na estação {StationId}: PM2.5 = {Value}", Alert.Pm25AboveLimit, reading.StationId, reading.Pm25);
    }
}
