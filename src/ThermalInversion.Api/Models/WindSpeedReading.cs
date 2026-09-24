using System.ComponentModel.DataAnnotations;
using Microsoft.EntityFrameworkCore;

namespace ThermalInversion.Api.Models;

/// <summary>Velocidade do vento (m/s).</summary>
[Index(nameof(StationId), nameof(Timestamp))]
public class WindSpeedReading : IReading
{
    public long Id { get; set; }

    [MaxLength(50)]
    public required string StationId { get; set; }

    [MaxLength(50)]
    public required string SensorId { get; set; }

    public double WindSpeedMs { get; set; }
    public DateTimeOffset Timestamp { get; set; }
}
