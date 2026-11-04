namespace CremaCompanion;

internal enum HandoffStage { Review, BackgroundSent, AlarmsSent, Verified, Uncertain }

internal sealed class HandoffProgress
{
    internal HandoffStage Stage { get; private set; } = HandoffStage.Review;
    internal bool CanSend(bool ready, bool curve) => ready &&
        (Stage == HandoffStage.Review || Stage == HandoffStage.BackgroundSent && curve);
    internal void Sent(bool background, bool ready, bool curve)
    {
        if (!CanSend(ready, curve) || background != (Stage == HandoffStage.Review))
            throw new InvalidOperationException("The preparation step is not ready.");
        Stage = background ? HandoffStage.BackgroundSent : HandoffStage.AlarmsSent;
    }
    internal void Verify(bool confirmed)
    {
        if (Stage != HandoffStage.AlarmsSent || !confirmed)
            throw new InvalidOperationException("Check the three alarm targets in Artisan first.");
        Stage = HandoffStage.Verified;
    }
    internal void Uncertain() => Stage = HandoffStage.Uncertain;
}
