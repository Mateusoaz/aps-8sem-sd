using System.ComponentModel.DataAnnotations;

namespace ThermalInversion.Api.Dtos;

/// <summary>Parâmetros de query comuns: ?from=...&amp;to=...&amp;limit=...</summary>
public class PeriodQuery
{
    private DateTimeOffset? _from;
    private DateTimeOffset? _to;

    // O Postgres (timestamptz) só aceita gravar/comparar DateTimeOffset em UTC,
    // então convertemos já na entrada (ex.: 2026-09-23T10:00-03:00 -> 13:00Z).
    public DateTimeOffset? From { get => _from; set => _from = value?.ToUniversalTime(); }
    public DateTimeOffset? To { get => _to; set => _to = value?.ToUniversalTime(); }

    [Range(1, 1000)]
    public int Limit { get; set; } = 100;
}
