using Flooding.Api.Data;
using Flooding.Api.Dtos;
using Flooding.Api.Infrastructure;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Flooding.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/monitoring-points")]
public class MonitoringPointsController(FloodingDbContext db, QueryCache cache) : ControllerBase
{
    // GET /api/v1/flooding/monitoring-points/PT-01/latest  ("nível atual por ponto de monitoramento", no cache por TTL segundos)
    [HttpGet("{monitoringPointId}/latest")]
    public async Task<ActionResult<LatestReadingsResponse>> GetLatest(string monitoringPointId, CancellationToken ct)
    {
        var latest = await cache.GetOrCreateAsync(Response, $"point-latest:{monitoringPointId}", () => QueryLatestAsync(monitoringPointId, ct));
        return latest is null ? NotFound() : latest;
    }

    private async Task<LatestReadingsResponse?> QueryLatestAsync(string monitoringPointId, CancellationToken ct)
    {
        var waterLevel = await db.WaterLevelReadings.AsNoTracking()
            .Where(r => r.MonitoringPointId == monitoringPointId).OrderByDescending(r => r.Timestamp).FirstOrDefaultAsync(ct);
        var rainfall = await db.RainfallReadings.AsNoTracking()
            .Where(r => r.MonitoringPointId == monitoringPointId).OrderByDescending(r => r.Timestamp).FirstOrDefaultAsync(ct);
        var flowRate = await db.FlowRateReadings.AsNoTracking()
            .Where(r => r.MonitoringPointId == monitoringPointId).OrderByDescending(r => r.Timestamp).FirstOrDefaultAsync(ct);

        if (waterLevel is null && rainfall is null && flowRate is null)
            return null;

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
