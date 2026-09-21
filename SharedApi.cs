using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Npgsql;

static class SharedApi
{
    public static async Task Initialize(string cs, string sql)
    {
        await using var connection = new NpgsqlConnection(cs);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(sql, connection);
        await command.ExecuteNonQueryAsync();
    }

    public static async Task<(long Id, bool Inserted)> Insert(
        string cs, string table, IReadOnlyDictionary<string, object?> values, object payload)
    {
        var json = JsonSerializer.Serialize(payload);
        var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(json))).ToLowerInvariant();
        var columns = values.Keys.ToList();
        var names = string.Join(',', columns.Append("payload_hash"));
        var parameters = string.Join(',', columns.Select((_, index) => $"@p{index}").Append("@hash"));

        await using var connection = new NpgsqlConnection(cs);
        await connection.OpenAsync();
        await using var command = connection.CreateCommand();
        command.CommandText = $"INSERT INTO {table}({names}) VALUES({parameters}) ON CONFLICT(payload_hash) DO NOTHING RETURNING id";
        for (var index = 0; index < columns.Count; index++)
        {
            var value = values[columns[index]];
            if (value is DateTimeOffset date) value = date.ToUniversalTime();
            command.Parameters.AddWithValue($"p{index}", value ?? DBNull.Value);
        }
        command.Parameters.AddWithValue("hash", hash);
        var inserted = await command.ExecuteScalarAsync();
        if (inserted is not null) return ((long)inserted, true);

        await using var existing = connection.CreateCommand();
        existing.CommandText = $"SELECT id FROM {table} WHERE payload_hash=@hash";
        existing.Parameters.AddWithValue("hash", hash);
        return ((long)(await existing.ExecuteScalarAsync())!, false);
    }

    public static async Task<List<JsonElement>> Query(string cs, string sql, params (string Name, object Value)[] parameters)
    {
        var rows = new List<JsonElement>();
        await using var connection = new NpgsqlConnection(cs);
        await connection.OpenAsync();
        await using var command = connection.CreateCommand();
        command.CommandText = $"SELECT to_jsonb(result) FROM ({sql}) result";
        foreach (var (name, value) in parameters) command.Parameters.AddWithValue(name, value);
        await using var reader = await command.ExecuteReaderAsync();
        while (await reader.ReadAsync()) rows.Add(JsonDocument.Parse(reader.GetString(0)).RootElement.Clone());
        return rows;
    }

    public static int Limit(int? value) => value is >= 1 and <= 1000 ? value.Value : 100;

    public static async Task<IResult> Ready(string cs, string schema)
    {
        try
        {
            await using var connection = new NpgsqlConnection(cs);
            await connection.OpenAsync();
            await using var command = new NpgsqlCommand("SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name=@schema)", connection);
            command.Parameters.AddWithValue("schema", schema);
            return (bool)(await command.ExecuteScalarAsync())!
                ? Results.Ok(new { status = "ready", database = "aps_monitoramento", schema })
                : Results.StatusCode(503);
        }
        catch { return Results.StatusCode(503); }
    }
}
