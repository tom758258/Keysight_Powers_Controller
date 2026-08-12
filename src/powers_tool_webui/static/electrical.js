export function resolveInputElectricalConstraint({
  parameterConstraints,
  electricalRatingsByModel,
  modelId,
  channel,
  parameterName
}) {
  const constraint = parameterConstraints?.[parameterName];
  const parameter = !constraint ? null : {
    attributes: {
      ...(constraint.min !== undefined ? { min: String(constraint.min) } : {}),
      ...(constraint.max !== undefined ? { max: String(constraint.max) } : {}),
      step: String(constraint.step ?? "any"),
      ...(constraint.description ? { title: String(constraint.description) } : {})
    },
    ...(constraint.exclusive_min !== undefined ? { exclusiveMin: String(constraint.exclusive_min) } : {})
  };
  const ratings = electricalRatingsByModel?.[modelId]?.channels;
  const selectedChannels = Array.isArray(channel) ? channel.map(String) : null;
  const channels = !Array.isArray(ratings) ? [] : channel === "all"
    ? ratings
    : ratings.filter((rating) => selectedChannels
      ? selectedChannels.includes(String(rating.channel))
      : String(rating.channel) === String(channel));
  const rating = channels.length ? {
    max_voltage: Math.min(...channels.map((item) => Number(item.max_voltage))),
    max_current: Math.min(...channels.map((item) => Number(item.max_current)))
  } : null;
  const electricalParameter = ["voltage", "start_voltage", "stop_voltage", "current"].includes(parameterName);
  const max = rating && electricalParameter
    ? String(parameterName === "current" ? rating.max_current : rating.max_voltage)
    : null;
  const override = max === null ? null : {
    attributes: {
      max,
      title: `Official independent-channel DC output rating: maximum ${max} ${parameterName === "current" ? "A" : "V"}.`
    }
  };
  return { parameter, rating, override };
}
