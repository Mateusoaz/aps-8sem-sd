using System.ComponentModel.DataAnnotations;
using Microsoft.EntityFrameworkCore;

namespace ThermalInversion.Api.Models;

/// <summary>Pressão atmosférica (hPa).</summary>
[Index(nameof(StationId), nameof(Timestamp))]
public class AtmosphericPressureReading : IReading
{
    public long Id { get; set; }

    [MaxLength(50)]
    public required string StationId { get; set; }

    [MaxLength(50)]
    public required string SensorId { get; set; }

    public double PressureHpa { get; set; }
    public DateTimeOffset Timestamp { get; set; }
}
