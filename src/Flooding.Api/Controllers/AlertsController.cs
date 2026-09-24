using Flooding.Api.Data;
using Flooding.Api.Dtos;
using Flooding.Api.Models;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Flooding.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/alerts")]
public class AlertsController(FloodingDbContext db) : ControllerBase
{
    // GET /api/v1/flooding/alerts?monitoringPointId=PT-01&from=...
    [HttpGet]
    public async Task<IReadOnlyList<Alert>> List(
        [FromQuery] string? monitoringPointId, [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        var query = db.Alerts.AsNoTracking();
        if (monitoringPointId is not null) query = query.Where(a => a.MonitoringPointId == monitoringPointId);

        return await query.InPeriod(period).ToListAsync(ct);
    }
}
