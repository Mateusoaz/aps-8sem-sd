using System.ComponentModel.DataAnnotations;
using Microsoft.EntityFrameworkCore;

namespace AirQuality.Api.Models;

[Index(nameof(Timestamp))]
[Index(nameof(StationId), nameof(Timestamp))]
public class Alert : IReading
{
    public const string Pm25AboveLimit = "PM25_ABOVE_LIMIT";

    public long Id { get; set; }

    [MaxLength(50)]
    public required string Type { get; set; }

    [MaxLength(50)]
    public required string StationId { get; set; }

    [MaxLength(50)]
    public required string AreaId { get; set; }

    /// <summary>Valor medido que disparou o alerta.</summary>
    public double Value { get; set; }

    /// <summary>Limite configurado no momento do alerta.</summary>
    public double Threshold { get; set; }

    [MaxLength(300)]
    public required string Message { get; set; }

    /// <summary>Momento da leitura que disparou o alerta.</summary>
    public DateTimeOffset Timestamp { get; set; }

    public DateTimeOffset CreatedAt { get; set; }
}
