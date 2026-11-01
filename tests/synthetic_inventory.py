"""Invented offline fixtures, not verified profiles or ownership claims.

Platform-shaped URLs exist only to exercise validators; never fetch them.
"""


def inventory(counts=None):
    counts = counts or {'instagram': 1, 'tiktok': 1, 'youtube': 1}
    accounts = []
    for platform, count in counts.items():
        for index in range(count):
            handle = f'sample_account_{index:02d}'
            accounts.append({
                'id': f'{platform}:{handle}', 'platform': platform,
                'name': f'Synthetic {platform} account {index}', 'handle': handle,
                'profile_url': (f'https://www.{platform}.com/' +
                                ('' if platform == 'instagram' else '@') + handle)
                               if index != 1 and not (platform == 'instagram' and index == 2) else None,
                'ownership': 'synthetic', 'sync_status': 'not_connected',
                'source': 'invented test fixture',
                'analytics': {'subscribers': 0, 'observed_at': None} if platform == 'youtube' else None,
            })
    return {'accounts': accounts, 'recorded_at': None}
