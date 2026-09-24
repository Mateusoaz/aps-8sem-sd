using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using ThermalInversion.Api.Data;
using ThermalInversion.Api.Dtos;
using ThermalInversion.Api.Options;

namespace ThermalInversion.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/occurrences")]
public class OccurrencesController(ThermalInversionDbContext db, IOptions<AlertOptions> options) : ControllerBase
{
    // GET /api/v1/thermal-inversion/occurrences?areaId=CENTRO&from=...&to=...
    // "Ocorrências por período": quantas leituras com inversão cada estação teve.
    // Sem from/to, considera as últimas 24 h.
    [HttpGet]
    public async Task<IReadOnlyList<OccurrenceResponse>> List(
        [FromQuery] string? stationId, [FromQuery] string? areaId,
        [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        var minGradient = options.Value.MinInversionGradientC;
        var to = period.To ?? DateTimeOffset.UtcNow;
        var from = period.From ?? to.AddHours(-24);

        var query = db.TemperatureProfiles.AsNoTracking()
            .Where(r => r.Timestamp >= from && r.Timestamp <= to)
            .Where(r => r.UpperTemperatureC - r.SurfaceTemperatureC > minGradient);
        if (stationId is not null) query = query.Where(r => r.StationId == stationId);
        if (areaId is not null) query = query.Where(r => r.AreaId == areaId);

        // GROUP BY station_id, area_id — executado no próprio Postgres
        var groups = await query
            .GroupBy(r => new { r.StationId, r.AreaId })
            .Select(g => new
            {
                g.Key.StationId,
                g.Key.AreaId,
                Count = g.Count(),
                First = g.Min(r => r.Timestamp),
                Last = g.Max(r => r.Timestamp),
            })
            .OrderByDescending(g => g.Count)
            .Take(period.Limit)
            .ToListAsync(ct);

        return groups
            .Select(g => new OccurrenceResponse(g.StationId, g.AreaId, g.Count, g.First, g.Last))
            .ToList();
    }
}
