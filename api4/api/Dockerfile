FROM mcr.microsoft.com/dotnet/sdk:9.0-alpine AS build
WORKDIR /src
COPY InversaoTermicaApi.csproj ./
RUN dotnet restore
COPY . ./
RUN dotnet publish -c Release -o /app/publish --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:9.0-alpine AS final
WORKDIR /app
USER $APP_UID
COPY --from=build /app/publish .
ENV ASPNETCORE_URLS=http://+:3004
EXPOSE 3004
ENTRYPOINT ["dotnet", "InversaoTermicaApi.dll"]
