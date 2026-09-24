using System.ComponentModel.DataAnnotations;
using Microsoft.EntityFrameworkCore;

namespace Flooding.Api.Models;

/// <summary>Chuva acumulada no ponto de monitoramento (mm).</summary>
[Index(nameof(MonitoringPointId), nameof(Timestamp))]
[Index(nameof(SensorId), nameof(Timestamp))]
public class RainfallReading : IReading
{
    public long Id { get; set; }

    [MaxLength(50)]
    public required string MonitoringPointId { get; set; }

    [MaxLength(50)]
    public required string SensorId { get; set; }

    public double RainfallMm { get; set; }
    public DateTimeOffset Timestamp { get; set; }
}
