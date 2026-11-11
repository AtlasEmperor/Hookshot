using System.Text.Json;
using HookshotBuilder;

namespace CasesFixture
{
    /// The C# copy of the update rules, the real Updater.cs, on the cases of tests/update_cases.json that name it
    static class Program
    {
        static string? Text(JsonElement arguments, int index) =>
            arguments[index].ValueKind == JsonValueKind.Null ? null : arguments[index].GetString();

        static object? Answer(string kind, JsonElement arguments) => kind switch
        {
            "track" => Updater.TrackOf(Text(arguments, 0)),
            "newer" => Updater.Newer(Text(arguments, 0), Text(arguments, 1)),
            "target" => Updater.Target(Text(arguments, 0), Text(arguments, 1), Text(arguments, 2)!),
            "builds_here" => Updater.BuildsHere(Text(arguments, 0)!, Text(arguments, 1), arguments[2].GetBoolean()),
            _ => throw new InvalidOperationException("The cases name a kind this fixture does not run: " + kind),
        };

        static object? Expected(JsonElement expect) => expect.ValueKind switch
        {
            JsonValueKind.String => expect.GetString(),
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            JsonValueKind.Null => null,
            _ => throw new InvalidOperationException("A case expects something that is no string, flag or null: " + expect),
        };

        static int Main(string[] arguments)
        {
            using var document = JsonDocument.Parse(File.ReadAllText(arguments[0]));
            var run = 0;
            var failed = 0;
            foreach (var testCase in document.RootElement.GetProperty("cases").EnumerateArray())
            {
                if (testCase.TryGetProperty("copies", out var copies) && !copies.EnumerateArray().Any(copy => copy.GetString() == "csharp"))
                    continue;
                run++;
                var answer = Answer(testCase.GetProperty("kind").GetString()!, testCase.GetProperty("args"));
                if (!Equals(answer, Expected(testCase.GetProperty("expect"))))
                {
                    failed++;
                    Console.WriteLine($"FAIL {testCase} answered {answer ?? "null"}");
                }
            }
            Console.WriteLine($"Update cases of the C# copy: {run - failed} passed, {failed} failed.");
            return failed == 0 && run > 0 ? 0 : 1;
        }
    }
}
