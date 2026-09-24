using System.ComponentModel.DataAnnotations;

namespace AirQuality.Api.Dtos;

// Corpo dos POSTs. "required" faz o JSON sem o campo ser rejeitado com 400;
// [Range] rejeita valores fisicamente impossíveis. Timestamp é opcional (padrão: agora, UTC).

public record CreateParticulateReadingRequest
{
    [Required, MaxLength(50)] public required string StationId { get; init; }
    [Required, MaxLength(50)] public required string SensorId { get; init; }
    [Required, MaxLength(50)] public required string AreaId { get; init; }
    [Range(0.0, 1000.0)] public required double Pm25 { get; init; }
    [Range(0.0, 2000.0)] public required double Pm10 { get; init; }
    public DateTimeOffset? Timestamp { get; init; }
}

public record CreateGasReadingRequest
{
    [Required, MaxLength(50)] public required string StationId { get; init; }
    [Required, MaxLength(50)] public required string SensorId { get; init; }
    [Required, MaxLength(50)] public required string AreaId { get; init; }
    [Range(0.0, 50000.0)] public required double Co2 { get; init; }
    [Range(0.0, 60000.0)] public required double Tvoc { get; init; }
    public DateTimeOffset? Timestamp { get; init; }
}

public record CreateEnvironmentReadingRequest
{
    [Required, MaxLength(50)] public required string StationId { get; init; }
    [Required, MaxLength(50)] public required string SensorId { get; init; }
    [Required, MaxLength(50)] public required string AreaId { get; init; }
    [Range(-50.0, 70.0)] public required double TemperatureC { get; init; }
    [Range(0.0, 100.0)] public required double HumidityPercent { get; init; }
    public DateTimeOffset? Timestamp { get; init; }
}
