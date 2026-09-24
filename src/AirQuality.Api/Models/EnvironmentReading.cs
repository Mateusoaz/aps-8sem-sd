using System.ComponentModel.DataAnnotations;
using Microsoft.EntityFrameworkCore;

namespace AirQuality.Api.Models;

/// <summary>Leitura ambiental da estação: temperatura (°C) e umidade relativa (%).</summary>
[Index(nameof(StationId), nameof(Timestamp))]
[Index(nameof(SensorId), nameof(Timestamp))]
[Index(nameof(AreaId), nameof(Timestamp))]
public class EnvironmentReading : IReading
{
    public long Id { get; set; }

    [MaxLength(50)]
    public required string StationId { get; set; }

    [MaxLength(50)]
    public required string SensorId { get; set; }

    [MaxLength(50)]
    public required string AreaId { get; set; }

    public double TemperatureC { get; set; }
    public double HumidityPercent { get; set; }
    public DateTimeOffset Timestamp { get; set; }
}
