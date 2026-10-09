
import requests

response = requests.post(
    "http://127.0.0.1:8000/evaluate",
    params={"sample_size": 100},
    timeout=270,
)
response.raise_for_status()
data = response.json()

if "avg_overall_proxy" in data:
    print(f"Companies evaluated: {data.get('sample_size', 'Unknown')}")
    print(f"Overall Average: {data['avg_overall_proxy']:.2f}/100")
    print(
        "Coverage Average: "
        f"{data['coverage_proxy_points_out_of_35']:.2f}/35"
    )
    print(f"Passes internal proxy: {data.get('passes_internal_proxy')}")
    print(f"Required overall score: {data.get('target_overall')}/100")
    print(
        "Required coverage score: "
        f"{data.get('coverage_qualifying_threshold')}/35"
    )
    print("\nScore breakdown:")
    for category, points in data.get("points", {}).items():
        print(f"  {category.replace('_', ' ').title()}: {points}")
else:
    print("Unexpected API response:")
    print(data)
