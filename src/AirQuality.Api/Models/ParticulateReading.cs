using System.ComponentModel.DataAnnotations;
using Microsoft.EntityFrameworkCore;

namespace AirQuality.Api.Models;

/// <summary>Leitura de material particulado (µg/m³).</summary>
[Index(nameof(StationId), nameof(Timestamp))]
[Index(nameof(SensorId), nameof(Timestamp))]
[Index(nameof(AreaId), nameof(Timestamp))]
public class ParticulateReading : IReading
{
    public long Id { get; set; }

    [MaxLength(50)]
    public required string StationId { get; set; }

    [MaxLength(50)]
    public required string SensorId { get; set; }

    [MaxLength(50)]
    public required string AreaId { get; set; }

    public double Pm25 { get; set; }
    public double Pm10 { get; set; }
    public DateTimeOffset Timestamp { get; set; }
}
