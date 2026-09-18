FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src

COPY TransitoApi.csproj ./
RUN dotnet restore TransitoApi.csproj
COPY . ./
RUN dotnet publish TransitoApi.csproj -c Release -o /app/publish --no-restore /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:9.0-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data \
    && chown app:app /data
WORKDIR /app
COPY --from=build /app/publish ./
ENV PORT=3003
ENV DB_PATH=/data/transito.db
EXPOSE 3003
USER app
ENTRYPOINT ["dotnet", "TransitoApi.dll"]
