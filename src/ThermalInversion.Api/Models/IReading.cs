namespace ThermalInversion.Api.Models;

/// <summary>Contrato comum de toda leitura de sensor: permite filtros genéricos por período.</summary>
public interface IReading
{
    DateTimeOffset Timestamp { get; }
}
