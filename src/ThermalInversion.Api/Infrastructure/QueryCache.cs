using System.Text.Json;
using Microsoft.Extensions.Options;
using StackExchange.Redis;

namespace ThermalInversion.Api.Infrastructure;

public class CacheOptions
{
    public const string SectionName = "Cache";

    /// <summary>Liga/desliga o cache sem recompilar (Cache__Enabled). A Etapa 5 compara com e sem.</summary>
    public bool Enabled { get; set; } = true;

    /// <summary>Por quantos segundos uma consulta fica guardada: é o quanto o dado pode estar desatualizado.</summary>
    public int TtlSeconds { get; set; } = 10;
}

/// <summary>
/// Conexão única com o Redis (ConnectionStrings__Redis). Sem a variável, o cache fica desligado.
/// AbortOnConnectFail = false: a API sobe mesmo com o Redis fora do ar e reconecta sozinha.
/// </summary>
public sealed class RedisConnection : IDisposable
{
    private readonly Lazy<ConnectionMultiplexer?> _multiplexer;

    public RedisConnection(IConfiguration configuration)
    {
        var connectionString = configuration.GetConnectionString("Redis");
        _multiplexer = new Lazy<ConnectionMultiplexer?>(() =>
        {
            if (string.IsNullOrEmpty(connectionString))
                return null;
            var options = ConfigurationOptions.Parse(connectionString);
            options.AbortOnConnectFail = false;
            options.ConnectTimeout = 2000;
            options.SyncTimeout = 1000;
            options.AsyncTimeout = 1000;
            options.ClientName = $"{ApiRoutes.ServiceName}@{AppInfo.Instance}";
            return ConnectionMultiplexer.Connect(options);
        });
    }

    public bool Configured => _multiplexer.Value is not null;

    public IDatabase? Database => _multiplexer.Value?.GetDatabase();

    public void Dispose()
    {
        if (_multiplexer.IsValueCreated)
            _multiplexer.Value?.Dispose();
    }
}

/// <summary>
/// Cache-aside das consultas agregadas: procura no Redis; se não achar, consulta o banco e guarda por TTL segundos.
/// O cache fica fora dos pods, então todas as réplicas aproveitam o mesmo resultado.
/// Cabeçalho X-Cache: HIT (veio do Redis), MISS (veio do banco), OFF (cache desligado) ou BYPASS (Redis fora do ar).
/// Redis fora do ar não derruba a consulta: ela vai direto ao banco.
/// </summary>
public class QueryCache(RedisConnection redis, IOptions<CacheOptions> options, ILogger<QueryCache> logger)
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private long _lastWarningTicks;

    public async Task<T?> GetOrCreateAsync<T>(HttpResponse response, string key, Func<Task<T?>> query) where T : class
    {
        var db = options.Value.Enabled ? redis.Database : null;
        if (db is null)
        {
            response.Headers["X-Cache"] = "OFF";
            return await query();
        }

        var fullKey = $"{ApiRoutes.ServiceName}:{key}";
        try
        {
            var cached = await db.StringGetAsync(fullKey);
            if (cached.HasValue)
            {
                response.Headers["X-Cache"] = "HIT";
                return JsonSerializer.Deserialize<T>((byte[])cached!, Json);
            }
        }
        catch (Exception ex) when (ex is RedisException or TimeoutException)
        {
            WarnThrottled(ex);
            response.Headers["X-Cache"] = "BYPASS";
            return await query();
        }

        var value = await query();
        response.Headers["X-Cache"] = "MISS";
        if (value is null)
            return null;

        try
        {
            await db.StringSetAsync(fullKey, JsonSerializer.SerializeToUtf8Bytes(value, Json),
                TimeSpan.FromSeconds(Math.Max(1, options.Value.TtlSeconds)));
        }
        catch (Exception ex) when (ex is RedisException or TimeoutException)
        {
            WarnThrottled(ex);
        }
        return value;
    }

    // Com o Redis fora do ar, toda consulta falharia no cache: um aviso a cada 10 s basta no log.
    private void WarnThrottled(Exception ex)
    {
        var now = DateTime.UtcNow.Ticks;
        var last = Interlocked.Read(ref _lastWarningTicks);
        if (now - last < TimeSpan.TicksPerSecond * 10 || Interlocked.CompareExchange(ref _lastWarningTicks, now, last) != last)
            return;
        logger.LogWarning("Redis indisponível ({Error}). Consultando direto no banco.", ex.Message);
    }
}
