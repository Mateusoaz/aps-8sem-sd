using System.ComponentModel.DataAnnotations;
using Microsoft.EntityFrameworkCore;

namespace ThermalInversion.Api.Models;

/// <summary>Perfil térmico: temperatura na superfície e numa altitude superior (°C), medidas pela mesma estação.</summary>
[Index(nameof(StationId), nameof(Timestamp))]
[Index(nameof(AreaId), nameof(Timestamp))]
public class TemperatureProfileReading : IReading
{
    public long Id { get; set; }

    [MaxLength(50)]
    public required string StationId { get; set; }

    /// <summary>Região da estação — usada no perfil térmico por área.</summary>
    [MaxLength(50)]
    public required string AreaId { get; set; }

    [MaxLength(50)]
    public required string SurfaceSensorId { get; set; }

    [MaxLength(50)]
    public required string UpperSensorId { get; set; }

    public double SurfaceTemperatureC { get; set; }
    public double UpperTemperatureC { get; set; }
    public DateTimeOffset Timestamp { get; set; }
}
