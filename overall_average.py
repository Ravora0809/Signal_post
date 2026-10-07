import requests

response = requests.post("http://127.0.0.1:8000/evaluate")
response.raise_for_status()

data = response.json()

# Find the list containing company evaluation records
if isinstance(data, list):
    results = data
elif "results" in data:
    results = data["results"]
elif "companies" in data:
    results = data["companies"]
elif "evaluations" in data:
    results = data["evaluations"]
else:
    # Find any list containing dictionaries with "overall"
    results = next(
        (
            value for value in data.values()
            if isinstance(value, list)
            and value
            and isinstance(value[0], dict)
            and "overall" in value[0]
        ),
        None
    )

if not results:
    print("Could not find company scores.")
    print("Response keys:", list(data.keys()))
    raise SystemExit(1)

overall_average = sum(
    float(company["overall"])
    for company in results
) / len(results)

coverage_average = sum(
    float(company["useful_information_points"])
    for company in results
) / len(results)

print(f"Overall Average: {overall_average:.2f}/100")
print(f"Coverage Average: {coverage_average:.2f}/35")