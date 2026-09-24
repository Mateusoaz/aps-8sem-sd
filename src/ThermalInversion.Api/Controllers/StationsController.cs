using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using ThermalInversion.Api.Data;
using ThermalInversion.Api.Dtos;

namespace ThermalInversion.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/stations")]
public class StationsController(ThermalInversionDbContext db) : ControllerBase
{
    // GET /api/v1/thermal-inversion/stations/EST-01/latest
    [HttpGet("{stationId}/latest")]
    public async Task<ActionResult<LatestReadingsResponse>> GetLatest(string stationId, CancellationToken ct)
    {
        var response = new LatestReadingsResponse(
            stationId,
            await db.TemperatureProfiles.AsNoTracking()
                .Where(r => r.StationId == stationId).OrderByDescending(r => r.Timestamp).FirstOrDefaultAsync(ct),
            await db.SoilMoistureReadings.AsNoTracking()
                .Where(r => r.StationId == stationId).OrderByDescending(r => r.Timestamp).FirstOrDefaultAsync(ct),
            await db.AirHumidityReadings.AsNoTracking()
                .Where(r => r.StationId == stationId).OrderByDescending(r => r.Timestamp).FirstOrDefaultAsync(ct),
            await db.AtmosphericPressureReadings.AsNoTracking()
                .Where(r => r.StationId == stationId).OrderByDescending(r => r.Timestamp).FirstOrDefaultAsync(ct),
            await db.WindSpeedReadings.AsNoTracking()
                .Where(r => r.StationId == stationId).OrderByDescending(r => r.Timestamp).FirstOrDefaultAsync(ct));

        if (response is { TemperatureProfile: null, SoilMoisture: null, AirHumidity: null, AtmosphericPressure: null, WindSpeed: null })
            return NotFound();

        return response;
    }

    // GET /api/v1/thermal-inversion/stations/EST-01/readings?from=...&to=...
    [HttpGet("{stationId}/readings")]
    public async Task<ReadingsResponse> GetReadings(string stationId, [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        return new ReadingsResponse(
            stationId,
            await db.TemperatureProfiles.AsNoTracking().Where(r => r.StationId == stationId).InPeriod(period).ToListAsync(ct),
            await db.SoilMoistureReadings.AsNoTracking().Where(r => r.StationId == stationId).InPeriod(period).ToListAsync(ct),
            await db.AirHumidityReadings.AsNoTracking().Where(r => r.StationId == stationId).InPeriod(period).ToListAsync(ct),
            await db.AtmosphericPressureReadings.AsNoTracking().Where(r => r.StationId == stationId).InPeriod(period).ToListAsync(ct),
            await db.WindSpeedReadings.AsNoTracking().Where(r => r.StationId == stationId).InPeriod(period).ToListAsync(ct));
    }
}
