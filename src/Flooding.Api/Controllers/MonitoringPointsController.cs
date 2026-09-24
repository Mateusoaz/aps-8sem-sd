using Flooding.Api.Data;
using Flooding.Api.Dtos;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Flooding.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/monitoring-points")]
public class MonitoringPointsController(FloodingDbContext db) : ControllerBase
{
    // GET /api/v1/flooding/monitoring-points/PT-01/latest  ("nível atual por ponto de monitoramento")
    [HttpGet("{monitoringPointId}/latest")]
    public async Task<ActionResult<LatestReadingsResponse>> GetLatest(string monitoringPointId, CancellationToken ct)
    {
        var waterLevel = await db.WaterLevelReadings.AsNoTracking()
            .Where(r => r.MonitoringPointId == monitoringPointId).OrderByDescending(r => r.Timestamp).FirstOrDefaultAsync(ct);
        var rainfall = await db.RainfallReadings.AsNoTracking()
            .Where(r => r.MonitoringPointId == monitoringPointId).OrderByDescending(r => r.Timestamp).FirstOrDefaultAsync(ct);
        var flowRate = await db.FlowRateReadings.AsNoTracking()
            .Where(r => r.MonitoringPointId == monitoringPointId).OrderByDescending(r => r.Timestamp).FirstOrDefaultAsync(ct);

        if (waterLevel is null && rainfall is null && flowRate is null)
            return NotFound();

        return new LatestReadingsResponse(monitoringPointId, waterLevel, rainfall, flowRate);
    }

    // GET /api/v1/flooding/monitoring-points/PT-01/readings?from=...  ("histórico das últimas horas")
    [HttpGet("{monitoringPointId}/readings")]
    public async Task<ReadingsResponse> GetReadings(string monitoringPointId, [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        return new ReadingsResponse(
            monitoringPointId,
            await db.WaterLevelReadings.AsNoTracking().Where(r => r.MonitoringPointId == monitoringPointId).InPeriod(period).ToListAsync(ct),
            await db.RainfallReadings.AsNoTracking().Where(r => r.MonitoringPointId == monitoringPointId).InPeriod(period).ToListAsync(ct),
            await db.FlowRateReadings.AsNoTracking().Where(r => r.MonitoringPointId == monitoringPointId).InPeriod(period).ToListAsync(ct));
    }
}
