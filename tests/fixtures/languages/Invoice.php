<?php

declare(strict_types=1);

namespace App\Billing;

use RuntimeException;

/** Regional tax rate (revised annually by finance). */
function tax_rate_for(string $region, ?int $year = null): float
{
    $year ??= (int) date('Y');
    if ($region === 'EU' && $year >= 2021) {
        return 0.21;
    }
    return match ($region) {
        'US' => 0.0,
        'CA' => 0.05,
        default => 0.10,
    };
}

interface Chargeable
{
    public function amountDue(): int;
}

final class Invoice implements Chargeable
{
    private array $lines = [];

    public function __construct(
        private readonly string $customerId,
        private string $currency = 'USD'
    ) {
    }

    public function addLine(string $label, int $cents): self
    {
        // public function addDiscount(string $code): self -- dropped in v3
        $this->lines[] = ['label' => $label, 'cents' => $cents];
        return $this;
    }

    public function amountDue(): int
    {
        $total = 0;
        foreach ($this->lines as $line) {
            $total += $line['cents'];
        }
        $format = function (int $cents): string {
            return sprintf('%s %.2f', $this->currency, $cents / 100);
        };
        if ($total < 0) {
            throw new RuntimeException('function amountDue() got {' . $format($total) . '}');
        }
        return $total;
    }
}
