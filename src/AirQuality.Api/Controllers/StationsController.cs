using AirQuality.Api.Data;
using AirQuality.Api.Dtos;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace AirQuality.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/stations")]
public class StationsController(AirQualityDbContext db) : ControllerBase
{
    // GET /api/v1/air-quality/stations/EST-01/latest
    [HttpGet("{stationId}/latest")]
    public async Task<ActionResult<LatestReadingsResponse>> GetLatest(string stationId, CancellationToken ct)
    {
        var particulate = await db.ParticulateReadings.AsNoTracking()
            .Where(r => r.StationId == stationId).OrderByDescending(r => r.Timestamp).FirstOrDefaultAsync(ct);
        var gases = await db.GasReadings.AsNoTracking()
            .Where(r => r.StationId == stationId).OrderByDescending(r => r.Timestamp).FirstOrDefaultAsync(ct);
        var environment = await db.EnvironmentReadings.AsNoTracking()
            .Where(r => r.StationId == stationId).OrderByDescending(r => r.Timestamp).FirstOrDefaultAsync(ct);

        if (particulate is null && gases is null && environment is null)
            return NotFound();

        return new LatestReadingsResponse(stationId, particulate, gases, environment);
    }

    // GET /api/v1/air-quality/stations/EST-01/readings?from=...&to=...
    [HttpGet("{stationId}/readings")]
    public async Task<ReadingsResponse> GetReadings(string stationId, [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        return new ReadingsResponse(
            await db.ParticulateReadings.AsNoTracking().Where(r => r.StationId == stationId).InPeriod(period).ToListAsync(ct),
            await db.GasReadings.AsNoTracking().Where(r => r.StationId == stationId).InPeriod(period).ToListAsync(ct),
            await db.EnvironmentReadings.AsNoTracking().Where(r => r.StationId == stationId).InPeriod(period).ToListAsync(ct));
    }
}
