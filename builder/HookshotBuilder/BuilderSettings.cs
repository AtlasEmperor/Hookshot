namespace HookshotBuilder;

/// What the player chose last time (the install folder, the game files, the shaders' tick): builder-settings.json beside the versions
sealed class BuilderSettings
{
    public string? Out { get; set; }
    public string? Nup { get; set; }
    public string? Romfs { get; set; }
    public string? Exefs { get; set; }
    public bool Dlss { get; set; }   // (NVIDIA DLSS ticked: NVIDIA's license was accepted)
    public bool Fsr { get; set; }    // (AMD FSR 4 ticked)
    public bool FsrLicense { get; set; }   // (AMD's license accepted when it was ticked: a tick saved before it was asked has not)
    public bool PrepareLater { get; set; }   // ("Prepare shaders now" unticked)
    public int? MemoryGb { get; set; }
    public string? Track { get; set; }   // (the update track chosen, Updater.cs: release, rc or nightly; null: these tools' own)   // (Build memory; null: Automatic. The updates use it too, as they show no menu)

    public static BuilderSettings? Load(string path) => Read(path).Settings;

    /// The settings saved at path: none when nothing was saved yet, or why they could not be read
    public static (BuilderSettings? Settings, string? Error) Read(string path)
    {
        try { return (System.Text.Json.JsonSerializer.Deserialize<BuilderSettings>(System.IO.File.ReadAllText(path)), null); }
        catch (Exception e) when (e is System.IO.FileNotFoundException or System.IO.DirectoryNotFoundException) { return (null, null); }
        catch (Exception e) when (e is System.IO.IOException or UnauthorizedAccessException or System.Text.Json.JsonException)
        {
            return (null, $"the builder's settings could not be read ({path}): {e.Message}");
        }
    }

    /// Written whole at path: beside it first, then moved over the old file, so a write cut short leaves the last settings readable
    public void Save(string path)
    {
        var part = path + ".part";
        System.IO.Directory.CreateDirectory(System.IO.Path.GetDirectoryName(path)!);
        System.IO.File.WriteAllText(part, System.Text.Json.JsonSerializer.Serialize(this));
        System.IO.File.Move(part, path, overwrite: true);
    }

    /// (the updates, from the launcher's Update and from the --update start after a self-update, begin before ApplySettings sets
    /// the tick from these settings: they read the saved choice itself. None saved: prepared, as the tick's default)
    public static bool PrepareNow(string path) => Load(path)?.PrepareLater != true;
}
