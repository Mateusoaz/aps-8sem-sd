using System.ComponentModel.DataAnnotations;
using Microsoft.EntityFrameworkCore;

namespace Flooding.Api.Models;

/// <summary>Vazão do córrego no ponto de monitoramento (m³/s).</summary>
[Index(nameof(MonitoringPointId), nameof(Timestamp))]
[Index(nameof(SensorId), nameof(Timestamp))]
public class FlowRateReading : IReading
{
    public long Id { get; set; }

    [MaxLength(50)]
    public required string MonitoringPointId { get; set; }

    [MaxLength(50)]
    public required string SensorId { get; set; }

    public double FlowRateM3s { get; set; }
    public DateTimeOffset Timestamp { get; set; }
}
