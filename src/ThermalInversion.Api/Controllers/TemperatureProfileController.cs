using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using ThermalInversion.Api.Data;
using ThermalInversion.Api.Dtos;
using ThermalInversion.Api.Models;
using ThermalInversion.Api.Services;

namespace ThermalInversion.Api.Controllers;

// Controller recebe JSON HTTP e delega persistência/regra de negócio às dependências injetadas.
[ApiController]
[Route(ApiRoutes.Base + "/temperature-profile")]
public class TemperatureProfileController(ThermalInversionDbContext db, AlertService alerts) : ControllerBase
{
    // POST /api/v1/thermal-inversion/temperature-profile
    [HttpPost]
    public async Task<ActionResult<TemperatureProfileReading>> Create(CreateTemperatureProfileReadingRequest request, CancellationToken ct)
    {
        // Converte o contrato de entrada (DTO) em entidade de banco e normaliza horário para UTC.
        var reading = new TemperatureProfileReading
        {
            StationId = request.StationId,
            AreaId = request.AreaId,
            SurfaceSensorId = request.SurfaceSensorId,
            UpperSensorId = request.UpperSensorId,
            SurfaceTemperatureC = request.SurfaceTemperatureC,
            UpperTemperatureC = request.UpperTemperatureC,
            Timestamp = request.Timestamp?.ToUniversalTime() ?? DateTimeOffset.UtcNow,
        };

        // A gravação precede a regra para que ela encontre esta leitura ao consultar o histórico.
        db.TemperatureProfiles.Add(reading);
        await db.SaveChangesAsync(ct);
        // Avaliação síncrona: o POST espera a comparação com o perfil anterior da estação.
        await alerts.EvaluateTemperatureProfileAsync(reading, ct);

        // 201 Created inclui o recurso criado e a URL que permite consultá-lo pelo ID.
        return CreatedAtAction(nameof(GetById), new { id = reading.Id }, reading);
    }

    // GET /api/v1/thermal-inversion/temperature-profile?stationId=EST-01&areaId=CENTRO&from=...
    [HttpGet]
    public async Task<IReadOnlyList<TemperatureProfileReading>> List(
        [FromQuery] string? stationId, [FromQuery] string? areaId, [FromQuery] string? sensorId,
        [FromQuery] PeriodQuery period, CancellationToken ct)
    {
        // AsNoTracking economiza trabalho em consultas que não vão alterar entidades.
        var query = db.TemperatureProfiles.AsNoTracking();
        if (stationId is not null) query = query.Where(r => r.StationId == stationId);
        if (areaId is not null) query = query.Where(r => r.AreaId == areaId);
        if (sensorId is not null) query = query.Where(r => r.SurfaceSensorId == sensorId || r.UpperSensorId == sensorId);

        // Os filtros são compostos em LINQ e executados pelo PostgreSQL quando materializados.
        return await query.InPeriod(period).ToListAsync(ct);
    }

    [HttpGet("{id:long}")]
    public async Task<ActionResult<TemperatureProfileReading>> GetById(long id, CancellationToken ct)
    {
        var reading = await db.TemperatureProfiles.AsNoTracking().FirstOrDefaultAsync(r => r.Id == id, ct);
        return reading is null ? NotFound() : reading;
    }
}
