using System.ComponentModel.DataAnnotations;
using Microsoft.EntityFrameworkCore;

namespace ThermalInversion.Api.Models;

/// <summary>Umidade do solo (%).</summary>
[Index(nameof(StationId), nameof(Timestamp))]
public class SoilMoistureReading : IReading
{
    public long Id { get; set; }

    [MaxLength(50)]
    public required string StationId { get; set; }

    [MaxLength(50)]
    public required string SensorId { get; set; }

    public double SoilMoisturePercent { get; set; }
    public DateTimeOffset Timestamp { get; set; }
}
