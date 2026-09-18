FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src

COPY QualidadeArApi.csproj ./
RUN dotnet restore QualidadeArApi.csproj
COPY . ./
RUN dotnet publish QualidadeArApi.csproj -c Release -o /app/publish --no-restore /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:9.0-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data \
    && chown app:app /data
WORKDIR /app
COPY --from=build /app/publish ./
ENV PORT=3001
ENV DB_PATH=/data/qualidade_ar.db
EXPOSE 3001
USER app
ENTRYPOINT ["dotnet", "QualidadeArApi.dll"]
