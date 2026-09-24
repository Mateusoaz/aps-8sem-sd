using System.ComponentModel.DataAnnotations;

namespace Flooding.Api.Dtos;

// Corpo dos POSTs. "required" faz o JSON sem o campo ser rejeitado com 400;
// [Range] rejeita valores fisicamente impossíveis. Timestamp é opcional (padrão: agora, UTC).

public record CreateWaterLevelReadingRequest
{
    [Required, MaxLength(50)] public required string MonitoringPointId { get; init; }
    [Required, MaxLength(50)] public required string SensorId { get; init; }
    [Range(0.0, 10000.0)] public required double WaterLevelCm { get; init; }
    public DateTimeOffset? Timestamp { get; init; }
}

public record CreateRainfallReadingRequest
{
    [Required, MaxLength(50)] public required string MonitoringPointId { get; init; }
    [Required, MaxLength(50)] public required string SensorId { get; init; }
    [Range(0.0, 1000.0)] public required double RainfallMm { get; init; }
    public DateTimeOffset? Timestamp { get; init; }
}

public record CreateFlowRateReadingRequest
{
    [Required, MaxLength(50)] public required string MonitoringPointId { get; init; }
    [Required, MaxLength(50)] public required string SensorId { get; init; }
    [Range(0.0, 100000.0)] public required double FlowRateM3s { get; init; }
    public DateTimeOffset? Timestamp { get; init; }
}
