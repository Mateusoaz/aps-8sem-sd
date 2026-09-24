using System.ComponentModel.DataAnnotations;

namespace ThermalInversion.Api.Dtos;

// Corpo dos POSTs. "required" faz o JSON sem o campo ser rejeitado com 400;
// [Range] rejeita valores fisicamente impossíveis. Timestamp é opcional (padrão: agora, UTC).

public record CreateTemperatureProfileReadingRequest
{
    [Required, MaxLength(50)] public required string StationId { get; init; }
    [Required, MaxLength(50)] public required string AreaId { get; init; }
    [Required, MaxLength(50)] public required string SurfaceSensorId { get; init; }
    [Required, MaxLength(50)] public required string UpperSensorId { get; init; }
    [Range(-50.0, 70.0)] public required double SurfaceTemperatureC { get; init; }
    [Range(-50.0, 70.0)] public required double UpperTemperatureC { get; init; }
    public DateTimeOffset? Timestamp { get; init; }
}

public record CreateSoilMoistureReadingRequest
{
    [Required, MaxLength(50)] public required string StationId { get; init; }
    [Required, MaxLength(50)] public required string SensorId { get; init; }
    [Range(0.0, 100.0)] public required double SoilMoisturePercent { get; init; }
    public DateTimeOffset? Timestamp { get; init; }
}

public record CreateAirHumidityReadingRequest
{
    [Required, MaxLength(50)] public required string StationId { get; init; }
    [Required, MaxLength(50)] public required string SensorId { get; init; }
    [Range(0.0, 100.0)] public required double AirHumidityPercent { get; init; }
    public DateTimeOffset? Timestamp { get; init; }
}

public record CreateAtmosphericPressureReadingRequest
{
    [Required, MaxLength(50)] public required string StationId { get; init; }
    [Required, MaxLength(50)] public required string SensorId { get; init; }
    [Range(300.0, 1100.0)] public required double PressureHpa { get; init; }
    public DateTimeOffset? Timestamp { get; init; }
}

public record CreateWindSpeedReadingRequest
{
    [Required, MaxLength(50)] public required string StationId { get; init; }
    [Required, MaxLength(50)] public required string SensorId { get; init; }
    [Range(0.0, 120.0)] public required double WindSpeedMs { get; init; }
    public DateTimeOffset? Timestamp { get; init; }
}
