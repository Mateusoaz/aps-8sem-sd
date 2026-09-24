using System.ComponentModel.DataAnnotations;
using Microsoft.EntityFrameworkCore;

namespace Flooding.Api.Models;

/// <summary>Nível da água no ponto de monitoramento (cm).</summary>
[Index(nameof(MonitoringPointId), nameof(Timestamp))]
[Index(nameof(SensorId), nameof(Timestamp))]
public class WaterLevelReading : IReading
{
    public long Id { get; set; }

    [MaxLength(50)]
    public required string MonitoringPointId { get; set; }

    [MaxLength(50)]
    public required string SensorId { get; set; }

    public double WaterLevelCm { get; set; }
    public DateTimeOffset Timestamp { get; set; }
}
