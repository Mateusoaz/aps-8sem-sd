FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src

COPY AlagamentosApi.csproj ./
RUN dotnet restore AlagamentosApi.csproj
COPY . ./
RUN dotnet publish AlagamentosApi.csproj -c Release -o /app/publish --no-restore /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:9.0-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data \
    && chown app:app /data
WORKDIR /app
COPY --from=build /app/publish ./
ENV PORT=3002
ENV DB_PATH=/data/alagamentos.db
EXPOSE 3002
USER app
ENTRYPOINT ["dotnet", "AlagamentosApi.dll"]
