package calc

import "testing"

func TestTotalArea(t *testing.T) {
	if TotalArea([]Shape{Square{Side: 1}}) != 2 {
		t.Fatal("unexpected area")
	}
}
