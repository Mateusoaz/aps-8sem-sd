using AirQuality.Api.Data;
using AirQuality.Api.Dtos;
using AirQuality.Api.Models;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace AirQuality.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/alerts")]
public class AlertsController(AirQualityDbContext db) : ControllerBase
{
    // GET /api/v1/air-quality/alerts?stationId=EST-01&areaId=CENTRO&from=...
    [HttpGet]
    public async Task<IReadOnlyList<Alert>> List(
        [FromQuery] string? stationId, [FromQuery] string? areaId,
        [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        var query = db.Alerts.AsNoTracking();
        if (stationId is not null) query = query.Where(a => a.StationId == stationId);
        if (areaId is not null) query = query.Where(a => a.AreaId == areaId);

        return await query.InPeriod(period).ToListAsync(ct);
    }
}
