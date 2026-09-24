using Flooding.Api.Data;
using Flooding.Api.Models;
using Flooding.Api.Options;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;

namespace Flooding.Api.Services;

/// <summary>
/// Regra: nível da água acima da cota de transbordamento.
/// O alerta é gerado quando o nível CRUZA a cota (leitura anterior abaixo ou inexistente), não a cada leitura.
/// Por enquanto roda de forma síncrona dentro do POST; numa etapa futura vira um consumidor de fila.
/// </summary>
public class AlertService(FloodingDbContext db, IOptions<AlertOptions> options, ILogger<AlertService> logger)
{
    public async Task EvaluateWaterLevelAsync(WaterLevelReading reading, CancellationToken ct)
    {
        var limit = options.Value.OverflowLevelCm;

        if (reading.WaterLevelCm <= limit)
            return;

        var previousLevel = await db.WaterLevelReadings
            .AsNoTracking()
            .Where(r => r.MonitoringPointId == reading.MonitoringPointId && r.Id != reading.Id && r.Timestamp <= reading.Timestamp)
            .OrderByDescending(r => r.Timestamp).ThenByDescending(r => r.Id)
            .Select(r => (double?)r.WaterLevelCm)
            .FirstOrDefaultAsync(ct);

        // Já estava acima da cota: o alerta deste episódio já foi emitido
        if (previousLevel > limit)
            return;

        db.Alerts.Add(new Alert
        {
            Type = Alert.WaterLevelAboveOverflow,
            MonitoringPointId = reading.MonitoringPointId,
            Value = reading.WaterLevelCm,
            Threshold = limit,
            Message = $"Nível da água ({reading.WaterLevelCm} cm) acima da cota de transbordamento ({limit} cm) no ponto {reading.MonitoringPointId}.",
            Timestamp = reading.Timestamp,
            CreatedAt = DateTimeOffset.UtcNow,
        });
        await db.SaveChangesAsync(ct);

        logger.LogWarning("Alerta {Type} no ponto {MonitoringPointId}: nível = {Value} cm",
            Alert.WaterLevelAboveOverflow, reading.MonitoringPointId, reading.WaterLevelCm);
    }
}
