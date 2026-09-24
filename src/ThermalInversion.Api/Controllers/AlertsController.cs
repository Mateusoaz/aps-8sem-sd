using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using ThermalInversion.Api.Data;
using ThermalInversion.Api.Dtos;
using ThermalInversion.Api.Models;

namespace ThermalInversion.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/alerts")]
public class AlertsController(ThermalInversionDbContext db) : ControllerBase
{
    // GET /api/v1/thermal-inversion/alerts?stationId=EST-01&areaId=CENTRO&from=...
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
