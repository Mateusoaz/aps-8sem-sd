using System.ComponentModel.DataAnnotations;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using ThermalInversion.Api.Data;
using ThermalInversion.Api.Dtos;
using ThermalInversion.Api.Infrastructure;
using ThermalInversion.Api.Options;

namespace ThermalInversion.Api.Controllers;

[ApiController]
[Route(ApiRoutes.Base + "/areas")]
public class AreasController(ThermalInversionDbContext db, IOptions<AlertOptions> options, QueryCache cache) : ControllerBase
{
    // GET /api/v1/thermal-inversion/areas/CENTRO/thermal-profile?hours=24
    // Consulta agregada "perfil térmico por região": contagens e médias. Fica no cache por TTL segundos.
    [HttpGet("{areaId}/thermal-profile")]
    public async Task<ThermalProfileResponse?> GetThermalProfile(string areaId, [FromQuery, Range(1, 720)] int hours = 24, CancellationToken ct = default)
        => await cache.GetOrCreateAsync(Response, $"thermal-profile:{areaId}:{hours}", () => ComputeThermalProfileAsync(areaId, hours, ct));

    private async Task<ThermalProfileResponse?> ComputeThermalProfileAsync(string areaId, int hours, CancellationToken ct)
    {
        var minGradient = options.Value.MinInversionGradientC;
        var to = DateTimeOffset.UtcNow;
        var from = to.AddHours(-hours);

        var profiles = db.TemperatureProfiles.Where(r => r.AreaId == areaId && r.Timestamp >= from && r.Timestamp <= to);

        var readingsCount = await profiles.CountAsync(ct);
        var inversionCount = await profiles.CountAsync(r => r.UpperTemperatureC - r.SurfaceTemperatureC > minGradient, ct);
        // O cast para double? faz a média de um conjunto vazio virar null em vez de lançar exceção
        var averageSurface = await profiles.AverageAsync(r => (double?)r.SurfaceTemperatureC, ct);
        var averageUpper = await profiles.AverageAsync(r => (double?)r.UpperTemperatureC, ct);
        var averageGradient = averageUpper - averageSurface;

        return new ThermalProfileResponse(
            areaId, from, to, readingsCount,
            averageSurface, averageUpper, averageGradient,
            inversionCount,
            InversionDetected: averageGradient > minGradient);
    }
}
