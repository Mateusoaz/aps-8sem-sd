using System.ComponentModel.DataAnnotations;
using Microsoft.EntityFrameworkCore;

namespace AirQuality.Api.Models;

/// <summary>Leitura de gases: CO2 (ppm) e compostos orgânicos voláteis totais — TVOC (ppb).</summary>
[Index(nameof(StationId), nameof(Timestamp))]
[Index(nameof(SensorId), nameof(Timestamp))]
[Index(nameof(AreaId), nameof(Timestamp))]
public class GasReading : IReading
{
    public long Id { get; set; }

    [MaxLength(50)]
    public required string StationId { get; set; }

    [MaxLength(50)]
    public required string SensorId { get; set; }

    [MaxLength(50)]
    public required string AreaId { get; set; }

    public double Co2 { get; set; }
    public double Tvoc { get; set; }
    public DateTimeOffset Timestamp { get; set; }
}
