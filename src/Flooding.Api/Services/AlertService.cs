using Flooding.Api.Data;
using Flooding.Api.Models;
using Flooding.Api.Options;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;

namespace Flooding.Api.Services;

/// <summary>
/// Regra: nível da água acima da cota de transbordamento.
/// O alerta é gerado quando o nível CRUZA a cota (leitura anterior abaixo ou inexistente), não a cada leitura.
/// Roda no consumidor da fila (AlertConsumer); se a fila estiver desligada ou fora do ar, dentro do próprio POST.
/// </summary>
public class AlertService(FloodingDbContext db, IOptions<AlertOptions> options, ILogger<AlertService> logger)
{
    /// <summary>Chamado pelo consumidor da fila: a mensagem traz só o id da leitura.</summary>
    public async Task EvaluateByIdAsync(long readingId, CancellationToken ct)
    {
        var reading = await db.WaterLevelReadings.AsNoTracking().FirstOrDefaultAsync(r => r.Id == readingId, ct);
        if (reading is null)
        {
            logger.LogWarning("Leitura {ReadingId} não encontrada: mensagem descartada.", readingId);
            return;
        }
        await EvaluateWaterLevelAsync(reading, ct);
    }

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

        // Idempotência: a fila entrega "pelo menos uma vez", então a mesma leitura pode ser avaliada duas vezes
        if (await db.Alerts.AnyAsync(a => a.Type == Alert.WaterLevelAboveOverflow && a.MonitoringPointId == reading.MonitoringPointId
                                          && a.Timestamp == reading.Timestamp, ct))
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
